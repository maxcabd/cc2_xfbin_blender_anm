import os
from itertools import chain
from typing import List
import time
import bmesh
import bpy
from bmesh.types import BMesh
from bpy.props import BoolProperty, StringProperty, CollectionProperty
from bpy.types import Action, Camera, Bone, Material, Object, Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector, Euler

from ..xfbin_lib.xfbin.structure.anm import (AnmDataPath, AnmEntry,
                                             AnmEntryFormat)
from ..xfbin_lib.xfbin.structure.nucc import (CoordNode, NuccChunkAnm, NuccChunkCamera, 
                                            NuccChunkLightDirc,
                                            NuccChunkLightPoint,
                                            NuccChunkAmbient,
                                            NuccChunkDynamics,
                                            NuccChunkClump, NuccChunkModel,
                                            NuccChunkModelHit,
                                            NuccChunkModelPrimitiveBatch,
                                            NuccChunkTexture,
                                            NuccChunkMaterial)

from ..xfbin_lib.xfbin.structure.nud import NudMesh
from ..xfbin_lib.xfbin.structure.xfbin import Xfbin
from ..xfbin_lib.xfbin.xfbin_reader import read_xfbin
from .common.coordinate_converter import *
from .common.helpers import (XFBIN_DYNAMICS_OBJ, XFBIN_ANMS_OBJ, XFBIN_TEXTURES_OBJ,
                             int_to_hex_str)
from .common.shaders import (shaders_dict, collision_mat)
from .panels.clump_panel import XfbinMaterialPropertyGroup
import cProfile

class ImportXFBIN(Operator, ImportHelper):
    """Loads an XFBIN file into blender"""
    bl_idname = "import_scene.xfbin"
    bl_label = "Import XFBIN"

    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})

    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    use_full_material_names: BoolProperty(
        name="Full material names",
        description="Display full name of materials in NUD meshes, instead of a shortened form")

    filter_glob: StringProperty(default="*.xfbin", options={"HIDDEN"})

    merge_verts: BoolProperty(name='Merge Vertices', default=False)

    import_textures: BoolProperty(name='Import Textures', default=True)

    skip_lod_tex: BoolProperty(name='Skip LOD Textures', default=False)

    import_modelhit: BoolProperty(name='Import Stage Collision', default=False)

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = True
        layout.use_property_decorate = True

        layout.prop(self, 'import_textures')
        layout.prop(self, 'skip_lod_tex')
        layout.prop(self, 'use_full_material_names')
        layout.prop(self, 'merge_verts')
        layout.prop(self, 'import_modelhit')

    def execute(self, context):
        import time

        # try:
        start_time = time.time()
        for file in self.files:
            
            self.filepath = os.path.join(self.directory, file.name)

            importer = XfbinImporter(
                self, self.filepath, self.as_keywords(ignore=("filter_glob",)))

            importer.read(context)

        elapsed_s = "{:.2f}s".format(time.time() - start_time)
        print("XFBIN import finished in " + elapsed_s)

        return {'FINISHED'}
        # except Exception as error:
        #     print("Catching Error")
        #     self.report({"ERROR"}, str(error))
        # return {'CANCELLED'}


class XfbinImporter:
    def __init__(self, operator: Operator, filepath: str, import_settings: dict):
        self.operator = operator
        self.filepath = filepath
        self.use_full_material_names = import_settings.get(
            "use_full_material_names")
        self.merge_verts = import_settings.get('merge_verts')
        self.import_textures = import_settings.get('import_textures')
        self.skip_lod_tex = import_settings.get('skip_lod_tex')
        self.import_modelhit = import_settings.get('import_modelhit')

    xfbin: Xfbin
    collection: bpy.types.Collection

    def read(self, context):
        self.xfbin = read_xfbin(self.filepath)
        self.collection = self.make_collection(context)

        texture_chunks: List[NuccChunkTexture] = list()

        # Create an empty object to store the texture chunks list
        empty_tex = bpy.data.objects.new(
            f'{XFBIN_TEXTURES_OBJ} [{self.collection.name}]', None)
        empty_tex.empty_display_size = 0

        # Link the empty to the collection
        self.collection.objects.link(empty_tex)


        #anm_chunks: List[NuccChunkAnm] = list()

        for page in self.xfbin.pages:
            # Add all texture chunks inside the xfbin
            texture_chunks.extend(page.get_chunks_by_type('nuccChunkTexture'))

            if self.import_textures:
                empty_tex.xfbin_texture_chunks_data.init_data(page.get_chunks_by_type('nuccChunkTexture'))

            #anm_chunks.extend(page.get_chunks_by_type('nuccChunkAnm'))

            clump = page.get_chunks_by_type('nuccChunkClump')

            if not len(clump):
                continue

            clump: NuccChunkClump = clump[0]
            armature_obj = self.make_armature(clump, context)
            self.make_objects(clump, armature_obj, context)

            # Set the armature as the active object after importing everything
            bpy.ops.object.mode_set(mode='OBJECT')
            context.view_layer.objects.active = armature_obj

            # Update the models' PointerProperty to use the models that were just imported
            armature_obj.xfbin_clump_data.update_models(armature_obj)

        for page in self.xfbin.pages:
            # get dynamics chunk
            dynamics = page.get_chunks_by_type('nuccChunkDynamics')

            if not len(dynamics):
                continue

            dynamics: NuccChunkDynamics = dynamics[0]
            self.make_dynamics(dynamics, context)

        
        anm_chunks: List[NuccChunkAnm] = list()
        cam_chunks: List[NuccChunkCamera] = list()
        lightdirc_chunks: List[NuccChunkLightDirc] = list()
        lightpoint_chunks: List[NuccChunkLightPoint] = list()
        ambient_chunks: List[NuccChunkLightPoint] = list()

        for page in self.xfbin.get_pages_by_type('NuccChunkAnm'):
            anm_chunks.extend(page.get_chunks_by_type('NuccChunkAnm'))
            cam_chunks.extend(page.get_chunks_by_type('NuccChunkCamera'))
            lightdirc_chunks.extend(page.get_chunks_by_type('NuccChunkLightDirc'))
            lightpoint_chunks.extend(page.get_chunks_by_type('NuccChunkLightPoint'))
            ambient_chunks.extend(page.get_chunks_by_type('NuccChunkAmbient'))


        # Create an empty object to store the anm chunks list
        empty_anm = bpy.data.objects.new(
            f'{XFBIN_ANMS_OBJ} [{self.collection.name}]', None)
        empty_anm.empty_display_size = 0

        self.collection.objects.link(empty_anm)

        empty_anm.xfbin_anm_chunks_data.init_data(anm_chunks, cam_chunks, lightdirc_chunks, lightpoint_chunks, ambient_chunks, context)

        for anm in anm_chunks: # Create camera and light objects for each anm if they exist
            for cam in cam_chunks:
                if anm.filePath != cam.filePath:
                    continue
                
                anm: NuccChunkAnm
                cam: NuccChunkCamera

                cam_data = bpy.data.cameras.new(f"{cam.name} ({anm.name})")
                cam_data.lens_unit = 'MILLIMETERS'
                cam_data.lens = focal_to_blender(cam.fov, 36.0)

                camera = bpy.data.objects.new(f"{cam.name} ({anm.name})", cam_data)
                camera.rotation_mode = 'QUATERNION'
                camera.animation_data_create()
                camera.animation_data.action = bpy.data.actions.get(f"{anm.name} (camera)")
                
                # Link the camera to the collection and to animation empty
                self.collection.objects.link(camera)
                camera.parent = empty_anm
            
            for lightdirc in lightdirc_chunks:
                if anm.filePath != lightdirc.filePath:
                    continue

                anm: NuccChunkAnm
                lightdirc: NuccChunkLightDirc

                lightdirc_data = bpy.data.lights.new(f"{lightdirc.name} ({anm.name})", 'SUN')
        
                light_dirc = bpy.data.objects.new(f"{lightdirc.name} ({anm.name})", lightdirc_data)
                light_dirc.rotation_mode = 'QUATERNION'
                light_dirc.animation_data_create()
                light_dirc.animation_data.action = bpy.data.actions.get(f"{anm.name} (lightdirc)")
                

                self.collection.objects.link(light_dirc)
                light_dirc.parent = empty_anm
            
            for lightpoint in lightpoint_chunks:
                if anm.filePath != lightpoint.filePath:
                    continue

                anm: NuccChunkAnm
                lightpoint: NuccChunkLightPoint

                lightpoint_data = bpy.data.lights.new(f"{lightpoint.name} ({anm.name})", 'POINT')
                lightpoint_data.use_custom_distance = True
        
                light_point = bpy.data.objects.new(f"{lightpoint.name} ({anm.name})", lightpoint_data)
                light_point.rotation_mode = 'QUATERNION'
                light_point.animation_data_create()
                light_point.animation_data.action = bpy.data.actions.get(f"{anm.name} (lightpoint)")
                
                self.collection.objects.link(light_point)
                light_point.parent = empty_anm

            for ambient in ambient_chunks:
                if anm.filePath != ambient.filePath:
                    continue

                anm: NuccChunkAnm
                ambient: NuccChunkAmbient


                # Since ambient light is environment light, we need to use the World settings
                # Therefore, we don't need to create a light object for it but a World object to the scene


                world = bpy.data.worlds.new(f"{ambient.name} ({anm.name})")
                world.use_nodes = True


                world.node_tree.nodes.new('ShaderNodeBackground')
                world.node_tree.nodes["Background"].inputs[0].default_value = (ambient.color[0], ambient.color[1], ambient.color[2], 1)
                world.node_tree.nodes["Background"].inputs[1].default_value = ambient.strength

                world.animation_data_create()
                world.animation_data.action = bpy.data.actions.get(f"{anm.name} (ambient)")

               
                context.scene.world = world
                

    def make_collection(self, context) -> bpy.types.Collection:
        """
        Build a collection to hold all of the objects and meshes from the GMDScene.
        :param context: The context used by the import process.
        :return: A collection which the importer can add objects and meshes to.
        """

        collection_name = os.path.basename(self.filepath).split('.')[0]
        collection = bpy.data.collections.new(collection_name)
        # Link the new collection to the currently active collection.
        context.collection.children.link(collection)
        return collection

    def make_dynamics(self, dynamics: NuccChunkDynamics, context):

        dynamics_obj = bpy.data.objects.new(
            f'{XFBIN_DYNAMICS_OBJ} [{dynamics.name}]', None)
        dynamics_obj.empty_display_size = 0

        # Set the Xfbin dynamics properties
        dynamics_obj.xfbin_dynamics_data.init_data(dynamics)

        # Use Spring Group names instead of indices for attached spring groups
        for col in dynamics_obj.xfbin_dynamics_data.collision_spheres:
            if col.attach_groups == True and col.attached_count > 0:
                for c in range(col.attached_count):
                    col.attached_groups[c].value = next((sp.name for sp in dynamics_obj.xfbin_dynamics_data.spring_groups if col.attached_groups[c].value == str(sp.spring_group_index)), None)

        self.collection.objects.link(dynamics_obj)

    def make_armature(self, clump: NuccChunkClump, context):
        # Avoid blender renaming meshes by making the armature name unique
        armature_name = f'{clump.name} [C]'

        armature = bpy.data.armatures.new(f"{armature_name}")
        armature.display_type = 'STICK'

        armature_obj = bpy.data.objects.new(f"{armature_name}", armature)
        armature_obj.show_in_front = True
        armature_obj['xfbin_clump'] = True

        # Set the Xfbin clump properties
        armature_obj.xfbin_clump_data.init_data(clump)

        self.collection.objects.link(armature_obj)

        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode='EDIT')

        bone_matrices = dict()

        def make_bone(node: CoordNode):

            # Find the local->world matrix for the parent bone, and use this to find the local->world matrix for the current bone
            if node.parent:
                parent_matrix = node.parent.matrix
            else:
                parent_matrix = Matrix.Identity(4)

            # Convert the node values
            pos = pos_cm_to_m(node.position)
            rot = rot_to_blender(node.rotation)
            sca = Vector(node.scale)

            # Set up the transformation matrix
            this_bone_matrix = parent_matrix @ Matrix.LocRotScale(pos, rot, sca)

            #print(f"-------------------{node.name}-------------------")
            #print(this_bone_matrix)

            # Add the matrix to the dictionary
            bone_matrices[node.name] = this_bone_matrix
            node.matrix = this_bone_matrix

            bone = armature.edit_bones.new(node.name)
            bone.use_relative_parent = False
            bone.use_deform = True

            # Having a long tail would offset the meshes parented to the mesh bones, so we avoid that for now
            bone.tail = Vector((0, 0.001, 0))

            bone.matrix = this_bone_matrix
            bone.parent = armature.edit_bones.get(node.parent.name) if node.parent else None

            # Store the signs of the node's scale to apply when exporting, as applying them here (if negative) will break the rotation
            bone['scale_signs'] = tuple(
                map(lambda x: -1 if x < 0 else 1, node.scale))

            # Store these unknown values to set when exporting
            bone['unk_float'] = node.unkFloat
            bone['unk_short'] = node.unkShort
            bone['matrix'] = node.matrix
            bone["orig_coords"] = [node.position, node.rotation, node.scale]

            relative_matrix = parent_matrix.inverted() @ this_bone_matrix
            dloc, drot, dsca = relative_matrix.decompose()
            #print(f"-------------------{node.name}-------------------")
            #print(dloc, drot, dsca)

            for child in node.children:
                make_bone(child)

        for root in clump.root_nodes:
            make_bone(root)
        
        
        bpy.ops.object.mode_set(mode='OBJECT')

        return armature_obj

    def make_objects(self, clump: NuccChunkClump, armature_obj: Object, context):
        vertex_group_list = [coord.node.name for coord in clump.coord_chunks]
        vertex_group_indices = {
            name: i
            for i, name in enumerate(vertex_group_list)
        }

        # Small QoL fix for JoJo "_f" models to show shortened material names
        clump_name = clump.name
        if clump_name.endswith('_f'):
            clump_name = clump_name[:-2]

        all_model_chunks = list(dict.fromkeys(
            chain(clump.model_chunks, *map(lambda x: x.model_chunks, clump.model_groups))))
        for nucc_model in all_model_chunks:

            if isinstance(nucc_model, NuccChunkModelPrimitiveBatch):
                self.make_primitive_batch(nucc_model, armature_obj, context)
                continue
            elif not (isinstance(nucc_model, NuccChunkModel) and nucc_model.nud):
                continue

            # Create modelhit object
            modelhit_obj = None
            if self.import_modelhit:
                modelhit_obj = self.make_modelhit(nucc_model.hit_chunk, armature_obj, context)
            
            nud = nucc_model.nud

            # Create an empty to store the NUD's properties, and set the armature to be its parent
            empty = bpy.data.objects.new(nucc_model.name, None)
            empty.empty_display_size = 0
            empty.parent = armature_obj

            # Link the empty to the collection
            self.collection.objects.link(empty)

            # Set the NUD properties
            empty.xfbin_nud_data.init_data(
                nucc_model, nucc_model.coord_chunk.name if nucc_model.coord_chunk else None)

            # Get the bone range that this NUD uses
            bone_range = nud.get_bone_range()

            # Set the mesh bone as the empty's parent bone, if it exists (it should)
            mesh_bone = None
            if nucc_model.coord_chunk:
                mesh_bone: Bone = armature_obj.data.bones.get(
                    nucc_model.coord_chunk.name)
                if mesh_bone and bone_range == (0, 0):
                    # create object constraints
                    empty.parent = armature_obj
                    empty.parent_type = 'BONE'
                    empty.parent_bone = mesh_bone.name

                    '''const = empty.constraints.new('CHILD_OF')
                    const.target = armature_obj
                    const.subtarget = mesh_bone.name
                    const.set_inverse_pending = False'''

            for group in nud.mesh_groups:
                for i, mesh in enumerate(group.meshes):
                    mat_chunk = nucc_model.material_chunks[i]
                    mat_name = mat_chunk.name
                    #blender_mat = self.make_material(mat_chunk, mesh, nud)

                    # Try to shorten the material name before adding it to the mesh name
                    if (not self.use_full_material_names) and mat_name.startswith(clump_name):
                        mat_name = mat_name[len(clump_name):].strip(' _')

                    # Add the material name to the group name because we don't have a way
                    # to differentiate between meshes in the same group
                    # The order of the mesh might matter, so the index is added here regardless
                    mesh_name = f'{group.name} ({i+1}) [{mat_name}]' if len(
                        mat_name) else group.name

                    overall_mesh = bpy.data.meshes.new(mesh_name)

                    # This list will get filled in nud_mesh_to_bmesh
                    custom_normals = list()
                    new_bmesh = self.nud_mesh_to_bmesh(
                        mesh, clump, vertex_group_indices, custom_normals)

                    # Convert the BMesh to a blender Mesh
                    new_bmesh.to_mesh(overall_mesh)
                    new_bmesh.free()

                    # Use the custom normals we made eariler
                    overall_mesh.create_normals_split()
                    overall_mesh.normals_split_custom_set_from_vertices(
                        custom_normals)
                    overall_mesh.auto_smooth_angle = 0
                    overall_mesh.use_auto_smooth = True

                    #add uv data
                    for i in range(len(mesh.vertices[0].uv)):
                        uv_layer = overall_mesh.uv_layers.new(name=f'UV_{i}')
                        for poly in overall_mesh.polygons:
                            for loop_index in poly.loop_indices:
                                loop = overall_mesh.loops[loop_index]
                                vert = mesh.vertices[loop.vertex_index]
                                uv_layer.data[loop_index].uv = uv_to_blender(vert.uv[i])
                    
                    #add vertex color data
                    if len(mesh.vertices[0].color) > 0:
                        color_layer = overall_mesh.vertex_colors.new(name='Color')
                        for poly in overall_mesh.polygons:
                            for loop_index in poly.loop_indices:
                                loop = overall_mesh.loops[loop_index]
                                vert = mesh.vertices[loop.vertex_index]
                                color_layer.data[loop_index].color = tuple(x / 255 for x in vert.color)

                    # Merge verts
                    if self.merge_verts == True:
                        merged = bmesh.new()
                        merged.from_mesh(overall_mesh)
                        bmesh.ops.remove_doubles(
                            merged, verts=merged.verts, dist=0.000001)
                        merged.to_mesh(overall_mesh)
                        merged.free()

                    # If we're not going to parent it, transform the mesh by the bone's matrix
                    if mesh_bone and bone_range != (0, 0):                        
                        #overall_mesh.transform(nucc_model.coord_chunk.node.matrix)
                        overall_mesh.transform(mesh_bone.matrix_local)

                    '''else:
                        loc, rot, scale = nucc_model.coord_chunk.node.matrix.decompose()
                        matrix = Matrix()
                        matrix = matrix @ Matrix.Scale(scale.x, 4, (1, 0, 0))
                        matrix = matrix @ Matrix.Scale(scale.y, 4, (0, 1, 0))
                        matrix = matrix @ Matrix.Scale(scale.z, 4, (0, 0, 1))
                        
                        overall_mesh.transform(matrix)'''


                    mesh_obj: bpy.types.Object = bpy.data.objects.new(
                        mesh_name, overall_mesh)
                    
                    #set active color
                    mesh_obj.data.color_attributes.render_color_index = 0
                    mesh_obj.data.color_attributes.active_color_index = 0

                    # Link the mesh object to the collection
                    self.collection.objects.link(mesh_obj)

                    # Parent the mesh to the empty
                    mesh_obj.parent = empty

                    #parent the modelhit to the empty
                    if modelhit_obj:
                        modelhit_obj.parent = empty

                    # Set the mesh as the active object to properly initialize its PropertyGroup
                    context.view_layer.objects.active = mesh_obj

                    # Set the NUD mesh properties
                    mesh_obj.xfbin_mesh_data.init_data(mesh, mat_chunk.name)

                    # Create the vertex groups for all bones (required)
                    for name in [coord.node.name for coord in clump.coord_chunks]:
                        mesh_obj.vertex_groups.new(name=name)

                    # Apply the armature modifier
                    modifier = mesh_obj.modifiers.new(
                        type='ARMATURE', name="Armature")
                    modifier.object = armature_obj

                    # Add the xfbin materials to the mesh
                    blender_mats = self.make_material(mat_chunk, mesh, nud, mesh_obj)
                    for blender_mat in blender_mats:
                        overall_mesh.materials.append(blender_mat)
                    
                    

    def make_modelhit(self, modelhit: NuccChunkModelHit, armature_obj: Object, context):

        if not isinstance(modelhit, NuccChunkModelHit):
            pass
        else:

            # Make an empty to store the modelhit's properties, and set the armature to be its parent
            hit_empty = bpy.data.objects.new(f'{modelhit.name}_[HIT]', None)
            hit_empty.empty_display_size = 0
            hit_empty.parent = armature_obj

            self.collection.objects.link(hit_empty)

            # Set the modelhit properties
            hit_empty.xfbin_modelhit_data.init_data(modelhit)

            for i, sec in enumerate(modelhit.vertex_sections):
                bm = bmesh.new()
                # Make a mesh to store the modelhit's vertex data
                mesh = bpy.data.meshes.new(f'{modelhit.name}_{i}')

                for v in range(0, len(sec.mesh_vertices), 3):
                    # add verts
                    bmv1 = bm.verts.new(sec.mesh_vertices[v])
                    bmv2 = bm.verts.new(sec.mesh_vertices[v+1])
                    bmv3 = bm.verts.new(sec.mesh_vertices[v+2])

                    # draw faces
                    face = bm.faces.new((bmv1, bmv2, bmv3))
                
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

                # clean up
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.scale(bm, vec=(0.01, 0.01, 0.01), verts=bm.verts)

                # apply the changes to the mesh we created
                bm.to_mesh(mesh)

                # free bmesh
                bm.free()

                # create a new object with our mesh data
                obj = bpy.data.objects.new(f'{modelhit.name}_{i}', mesh)

                # link the object to the current collection
                self.collection.objects.link(obj)

                # parent the object to the empty
                obj.parent = hit_empty

                # create a material for the object
                mat = collision_mat(obj.name)
                obj.data.materials.append(mat)

                obj.xfbin_modelhit_mesh_data.init_data(sec)
            return hit_empty

    def make_primitive_batch(self, batch: NuccChunkModelPrimitiveBatch, armature_obj: Object, context):

        # Make an empty and set the armature to be its parent
        primitive_empty = bpy.data.objects.new(f'{batch.name}_[PRIMITIVE]', None)
        primitive_empty.empty_display_size = 0
        primitive_empty.parent = armature_obj

        self.collection.objects.link(primitive_empty)

        vertex = 0
        for i, mesh in enumerate(batch.meshes):
            obj = self.make_primitive_vertex(f"{batch.name}_{i}",
                                             batch.primitive_vertex_chunk.vertices[vertex:vertex+mesh.vertex_count],
                                             armature_obj, armature_obj.data.bones[mesh.parent_bone].name)
            
            #transform the object by the bone matrix
            obj.data.transform(armature_obj.data.bones[mesh.parent_bone].matrix_local.to_4x4())
            
            # link the object to the current collection
            self.collection.objects.link(obj)

            # parent the object to the empty
            obj.parent = primitive_empty

        #TODO: use batch.material_chunk to make a material

        '''mat: XfbinMaterialPropertyGroup = self.materials.add()
        material = mat.init_data(batch.material_chunk)'''

    def make_primitive_vertex(self, name, vertices, armature_obj: Object, parent_bone):

        bm = bmesh.new()
        # Make a mesh to store the primitive vertex data
        mesh = bpy.data.meshes.new(f'{name}')

        uv = [v.uv for v in vertices]
        color = [v.color for v in vertices]

        for i in range(0, len(vertices), 3):
            # add verts
            bmv1 = bm.verts.new(vertices[i].position)
            bmv1.normal = vertices[i].normal
            bmv2 = bm.verts.new(vertices[i+1].position)
            bmv2.normal = vertices[i+1].normal
            bmv3 = bm.verts.new(vertices[i+2].position)
            bmv3.normal = vertices[i+2].normal

            # draw faces
            face = bm.faces.new((bmv1, bmv2, bmv3))
        
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # clean up
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        bmesh.ops.scale(bm, vec=(0.01, 0.01, 0.01), verts=bm.verts)

        # apply the changes to the mesh we created
        bm.to_mesh(mesh)

        #add uv data
        mesh.uv_layers.new(name='UVMap')
        uv_layer = mesh.uv_layers.active.data
        for i, uv in enumerate(uv_layer):
            uv.uv = vertices[i].uv
        
        #add color data
        mesh.vertex_colors.new(name='Color')
        color_layer = mesh.vertex_colors.active.data
        for i, color in enumerate(color_layer):
            color.color = vertices[i].color

        # free bmesh
        bm.free()
        
        # create a new object with our mesh data
        obj = bpy.data.objects.new(f'{name}', mesh)

        return obj

    def make_material(self, xfbin_mat: NuccChunkMaterial, mesh, nud, mesh_obj) -> Material:
        material_name = xfbin_mat.name
        materials = []
        # use existing materials
        if not bpy.data.materials.get(material_name):
            
            #for i in range(len(mesh.materials)):
            meshmat = mesh.materials[0]
            
            shader = int_to_hex_str(meshmat.flags, 4)
            

            if shader in shaders_dict:
                material = shaders_dict.get(shader)(
                    self, meshmat, xfbin_mat, material_name, mesh_obj, material_name)
                materials.append(material)
            else:
                material = shaders_dict.get("default")(
                    self, meshmat, xfbin_mat, material_name, mesh_obj, material_name)

                materials.append(material)
            
        else:
            material = bpy.data.materials.get(material_name)
            materials.append(material)

        return materials

    def nud_mesh_to_bmesh(self, mesh: NudMesh, clump: NuccChunkClump, vertex_group_indices, custom_normals) -> BMesh:
        bm = bmesh.new()

        deform = bm.verts.layers.deform.new("Vertex Weights")

        # Vertices
        for i in range(len(mesh.vertices)):
            vtx = mesh.vertices[i]
            vert = bm.verts.new(pos_scaled_to_blender(vtx.position))

            # Tangents cannot be applied
            if vtx.normal:
                normal = pos_to_blender(vtx.normal)
                custom_normals.append(normal)
                vert.normal = normal

            if vtx.bone_weights:
                for bone_id, bone_weight in zip(vtx.bone_ids, vtx.bone_weights):
                    if bone_weight > 0:
                        vertex_group_index = vertex_group_indices[clump.coord_chunks[bone_id].name]
                        vert[deform][vertex_group_index] = bone_weight

        # Set up the indexing table inside the bmesh so lookups work
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()

        # For each triangle, add it to the bmesh
        for mesh_face in mesh.faces:
            tri_idxs = mesh_face

            # Skip "degenerate" triangles
            if len(set(tri_idxs)) != 3:
                continue

            try:
                face = bm.faces.new(
                    (bm.verts[tri_idxs[0]], bm.verts[tri_idxs[1]], bm.verts[tri_idxs[2]]))
                face.smooth = True
            except Exception as e:
                # We might get duplicate faces for some reason
                # print(e)
                pass

        return bm
    

def make_actions(anm: NuccChunkAnm, context) -> List[Action]:
    actions: List[bpy.types.Action] = list()

    try:
        for entry in anm.other_entries:
            entry: AnmEntry

            # TODO: Some anm have no clumps for some reason, just skip them until we know why
            if not len(anm.clumps):
                continue

        
            action = bpy.data.actions.new(
                f'{anm.name} ({AnmEntryFormat(entry.entry_format).name.lower()})')
            
            group_name = action.groups.new(anm.name).name

           
            for curve in entry.curves:
                if curve is None or (not len(curve.keyframes)) or curve.data_path == AnmDataPath.UNKNOWN:
                    continue

                frames = list(
                    map(lambda x: frame_to_blender(x.frame), curve.keyframes))
                
                values = convert_anm_values(curve.data_path, list(
                    map(lambda x: x.value, curve.keyframes)))

                if curve.data_path == AnmDataPath.CAMERA:
                    data_path = 'data.lens'
                
                elif curve.data_path == AnmDataPath.COLOR:
                    data_path = 'data.color'
                
                elif curve.data_path == AnmDataPath.ENERGY:
                    data_path = 'data.energy'

                elif curve.data_path == AnmDataPath.RADIUS:
                    data_path = 'data.shadow_soft_size'

                elif curve.data_path == AnmDataPath.CUTOFF:
                    data_path = 'data.cutoff_distance'

                else:
                    data_path = f'{AnmDataPath(curve.data_path).name.lower()}'
                
            
                for i in range(len(values[0])):
                    fc = action.fcurves.new(
                        data_path=data_path, index=i, action_group=group_name)
                    fc.keyframe_points.add(len(frames))
                    fc.keyframe_points.foreach_set('co', [x for co in list(
                        map(lambda f, v: (f, v[i]), frames, values)) for x in co])
                    fc.update()
                
                if entry.entry_format == AnmEntryFormat.AMBIENT:
                    world = bpy.data.worlds["World"]
                    if not world.use_nodes:
                        world.use_nodes = True

                    node_tree = world.node_tree

                    if "Background" not in node_tree.nodes:
                        bg_node = node_tree.nodes.new(type='ShaderNodeBackground')
                        bg_node.name = "Background"
                    else:
                        bg_node = node_tree.nodes["Background"]
                    
                    if curve.data_path == AnmDataPath.COLOR:
                        for i in range(4):  # RGBA
                            fc = action.fcurves.new(
                                data_path=f'node_tree.nodes["Background"].inputs[0].default_value', 
                                index=i, 
                                action_group=group_name
                            )
                            fc.keyframe_points.add(len(frames))
                            fc.keyframe_points.foreach_set('co', [x for co in list(
                                map(lambda f, v: (f, v[i]), frames, values)) for x in co])
                            fc.update()
                      
       
        
        for clump in anm.clumps:
            action = bpy.data.actions.new(f'{anm.name} ({clump.name})')

            arm_obj = bpy.data.objects.get(clump.chunk.name)
            if arm_obj is None:
                arm_obj = bpy.data.objects.get(clump.chunk.name + ' [C]')

            arm_sca = dict()
            arm_mat = dict()
            arm_rot = dict()

            if arm_obj is not None:
                context.view_layer.objects.active = arm_obj
                bpy.ops.object.mode_set(mode='EDIT')

                for arm_bone in arm_obj.data.edit_bones:
                    arm_sca[arm_bone.name] = arm_bone.get('scale_signs')
                    arm_mat[arm_bone.name] = Matrix(arm_bone.get('matrix'))

                
                bpy.ops.object.mode_set(mode='POSE')
                for arm_bone in arm_obj.pose.bones:
                    arm_bone.rotation_mode = "QUATERNION"
                    
                bpy.ops.object.mode_set(mode='EDIT')

            for bone in clump.bones:
                group_name = action.groups.new(bone.name).name

                if bone.anm_entry is None:
                    continue



                mat_parent = arm_mat.get(bone.parent.name, Matrix.Identity(
                    4)) if bone.parent else Matrix.Identity(4)
                mat = arm_mat.get(bone.name, Matrix.Identity(4))

                mat = (mat_parent.inverted() @ mat)
                loc, rot, sca = mat.decompose()
                rot.invert()
                sca = Vector(map(lambda a: 1/a, sca))

                rotate_vector = arm_rot.get(bone.name,Euler([0,0,0]))

                bone_path = f'pose.bones["{group_name}"]'

                bone_parent = False
                if bone.parent:
                    bone_parent = True


                for curve in bone.anm_entry.curves:
                    if curve is None or (not len(curve.keyframes)) or curve.data_path == AnmDataPath.UNKNOWN:
                        continue

                    frames = list(
                        map(lambda x: frame_to_blender(x.frame), curve.keyframes))

                    if (bone.parent != None):
                        values = convert_anm_values_tranformed(curve.data_path, list(
                            map(lambda x: x.value, curve.keyframes)), loc, rot, sca, rotate_vector, bone_parent)
                    else:
                        values = convert_anm_values_tranformed_root(curve.data_path, list(
                            map(lambda x: x.value, curve.keyframes)), loc, rot, sca)

                    if (curve.data_path == AnmDataPath.ROTATION_EULER):
                        curve.data_path = AnmDataPath.ROTATION_QUATERNION

                    data_path = f'{bone_path}.{AnmDataPath(curve.data_path).name.lower()}'

                    for i in range(len(values[0])):
                        fc = action.fcurves.new(
                            data_path=data_path, index=i, action_group=group_name)
                        fc.keyframe_points.add(len(frames))
                        fc.keyframe_points.foreach_set('co', [x for co in list(
                            map(lambda f, v: (f, v[i]), frames, values)) for x in co])

                        fc.update()

            """for clump in anm.clumps:
                for material in clump.materials:
                    action = bpy.data.actions.new(f'{anm.name} ({material.name})')

                    group_name = action.groups.new(anm.name).name


                    node_tree = bpy.data.materials.get(material.name).node_tree
                    mapping_node = node_tree.nodes.get("Mapping")

                  
                    if mapping_node is None:
                        mapping_node = node_tree.nodes.new(type='ShaderNodeMapping')
                        mapping_node.name = "Mapping"
                        mapping_node.location = (0, 0)
                
                    for curve in material.anm_entry.curves:
                        if curve is None or (not len(curve.keyframes)) or curve.data_path == AnmDataPath.UNKNOWN:
                            continue

                        frames = list(map(lambda x: frame_to_blender(x.frame), curve.keyframes))
                        values = list(map(lambda x: x.value, curve.keyframes))

                        

                        if curve.data_path == AnmDataPath.U1_LOCATION:
                            for frame, value in zip(frames, values):
                                mapping_node.inputs['Location'].default_value[0] = value[0]
                                mapping_node.inputs['Location'].keyframe_insert(data_path="default_value", index=0, frame=frame, group=group_name)


                        if curve.data_path == AnmDataPath.V1_LOCATION:
                            for frame, value in zip(frames, values):
                                mapping_node.inputs['Location'].default_value[1] = value[0]
                                mapping_node.inputs['Location'].keyframe_insert(data_path="default_value", index=1, frame=frame, group=group_name)
                        
                        if curve.data_path == AnmDataPath.U1_SCALE:
                            for frame, value in zip(frames, values):
                                mapping_node.inputs['Scale'].default_value[0] = value[0]
                                mapping_node.inputs['Scale'].keyframe_insert(data_path="default_value", index=0, frame=frame, group=group_name)
                        
                        if curve.data_path == AnmDataPath.V1_SCALE:
                            for frame, value in zip(frames, values):
                                mapping_node.inputs['Scale'].default_value[1] = value[0]
                                mapping_node.inputs['Scale'].keyframe_insert(data_path="default_value", index=1, frame=frame, group=group_name)"""
                                

            actions.append(action)
    except Exception as e:
        print(e)

    bpy.ops.object.posemode_toggle()

    context.scene.render.fps = 30

    return actions




def convert_anm_values_tranformed(data_path: AnmDataPath, values, loc: Vector, rot: Quaternion, sca: Vector, rotate_vector: Euler, parent: bool):
    if data_path == AnmDataPath.LOCATION:
        updated_values = list()
        for value_loc in values:
            vec_loc = Vector([value_loc[0],value_loc[1],value_loc[2]])
            vec_loc.rotate(rot)
            updated_values.append(vec_loc)
        updated_loc = loc
        updated_loc.rotate(rot)

        return list(map(lambda x: ((x*0.01) - updated_loc)[:], updated_values))
    if data_path == AnmDataPath.ROTATION_EULER:
        return list(map(lambda x: (rot @ ((rot_to_blender(x).to_quaternion()).to_euler()).to_quaternion())[:], values))
    if data_path == AnmDataPath.ROTATION_QUATERNION:
        quat_list = list()
        updated_rot2 = Euler([math.radians(rotate_vector[0]),math.radians(rotate_vector[1]),math.radians(rotate_vector[2])]).to_quaternion()
        for rotation in values:
            q = rot.conjugated().copy()
            q.rotate(rot)
            quat = q
            q = rot.conjugated().copy()
            if parent == False:
                q.rotate(Quaternion((rotation[3], *rotation[:3])).conjugated())
            else:
                q.rotate(Quaternion((rotation[3], *rotation[:3])))
            quat.rotate(q.conjugated())
            quat_list.append(quat)
        return quat_list
    if data_path == AnmDataPath.SCALE:
        return list(map(lambda x: (Vector(([abs(y) for y in x])))[:], values))
    return values


def convert_anm_values_tranformed_root(data_path: AnmDataPath, values, loc: Vector, rot: Quaternion, sca: Vector):
    if data_path == AnmDataPath.LOCATION:
        return list(map(lambda x: (loc + pos_cm_to_m(x))[:], values))
    if data_path == AnmDataPath.ROTATION_EULER:
        return list(map(lambda x: (((rot_to_blender(x).to_quaternion()).to_euler()).to_quaternion())[:], values))
    if data_path == AnmDataPath.ROTATION_QUATERNION:
        return list(map(lambda x: (Quaternion((x[3], *x[:3])).inverted())[:], values))
    if data_path == AnmDataPath.SCALE:
        return list(map(lambda x: (Vector(([abs(y) for y in x])))[:], values))
    return values


def convert_anm_values(data_path: AnmDataPath, values):
    if data_path == AnmDataPath.LOCATION:
        return list(map(lambda x: pos_cm_to_m_tuple(x), values))
    if data_path == AnmDataPath.ROTATION_EULER:
        return list(map(lambda x: rot_to_blender(x)[:], values))
    if data_path == AnmDataPath.ROTATION_QUATERNION:
        return list(map(lambda x: Quaternion((x[3], *x[:3])).inverted()[:], values))
    if data_path == AnmDataPath.SCALE:
        return list(map(lambda x: Vector(([abs(y) for y in x]))[:], values))
    if data_path == AnmDataPath.CAMERA:
        return list(map(lambda x: (focal_to_blender(x[0], 36.0),), values))

    return values


def menu_func_import(self, context):
    self.layout.operator(ImportXFBIN.bl_idname,
                         text='XFBIN Model Container (.xfbin)')