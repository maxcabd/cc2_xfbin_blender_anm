from typing import List

import bpy
from bpy.props import (BoolProperty, CollectionProperty, IntProperty,
                       StringProperty)
from bpy.types import Panel, PropertyGroup
from ...xfbin_lib.xfbin.structure.nucc import NuccChunkTexture
from ...xfbin_lib.xfbin.structure.nut import Nut, NutTexture, Pixel_Formats
from ..common.helpers import XFBIN_TEXTURES_OBJ
from .common import draw_xfbin_list
#from ..common.shaders import F00A, _02_F00A, _05_F00D, _01_F003, _05_F002, _07_F002, _07_F010, _07_F00D, _01_F002, _01_F008, E002
from ...xfbin_lib.xfbin.structure import dds
from ...xfbin_lib.xfbin.structure.br import br_dds


class NutTexturePropertyGroup(PropertyGroup):

    name: StringProperty(name="Name")
    image: bpy.props.PointerProperty(type=bpy.types.Image, name="Image")
    index: IntProperty(name="Index")
    width: IntProperty(name="Width", default=0)
    height: IntProperty(name="Height", default=0)
    pixel_format: IntProperty(name="Pixel Format", default=0)
    mipmap_count: IntProperty(name="Mipmap Count", default=0)
    cubemap_format: IntProperty(name="Cubemap Format", default=0)
    cubemap_size: IntProperty(name="Cubemap Size", default=0)
    is_cubemap: BoolProperty(name="Is Cubemap", default=False)
    
    def update_name(self):
        #update texture count
        data: TextureChunksListPropertyGroup = bpy.context.object.xfbin_texture_chunks_data
        chunks = data.texture_chunks
        index = data.texture_chunk_index

        chunks[index].texture_count = len(chunks[index].textures)

        self.name = f'{chunks[index].name}_{len(chunks[index].textures) - 1}'

    def init_data(self, nut_texture: NutTexture, tex_name, path = ''):
        self.name = tex_name
        self.width = nut_texture.width
        self.height = nut_texture.height
        self.pixel_format = nut_texture.pixel_format
        self.mipmap_count = nut_texture.mipmap_count
        self.is_cubemap = nut_texture.is_cube_map

        if self.cubemap_format & 0x200:
            self.cubemap_format = nut_texture.cubemap_format
            self.cubemap_size = nut_texture.cubemap_size
            self.cubemap_faces = nut_texture.cubemap_faces

        #convert Nut Texture to DDS
        self.texture_data = dds.NutTexture_to_DDS(nut_texture)


        if bpy.data.images.get(self.name):
            #update existing image
            self.image = bpy.data.images[self.name]
            self.image.pack(data=self.texture_data, data_len=len(self.texture_data))
            self.image.source = 'FILE'
            self.image.filepath_raw = path
            self.image.use_fake_user = True
            self.image['nut_pixel_format'] = self.pixel_format        

        else:
            #create new image
            self.image = bpy.data.images.new(tex_name, width=self.width, height=self.height)
            self.image.pack(data=self.texture_data, data_len=len(self.texture_data))
            self.image.source = 'FILE'
            self.image.filepath_raw = path
            self.image.use_fake_user = True
            #add custom properties to the image
            self.image['nut_pixel_format'] = self.pixel_format  
            self.image['nut_mipmaps_count'] = self.mipmap_count      


# bpy.props don't support inheritance...
# So this is mostly a copy of XfbinNutTexturePropertyGroup
class XfbinTextureChunkPropertyGroup(PropertyGroup):
    def update_texture_name(self, context):
        self.update_name()

    texture_name: StringProperty(
        name='Name',
        default='new_texture',
        update=update_texture_name,
    )

    path: StringProperty(
        name='Path',
        description='XFBIN chunk path that will be used for identifying the texture in the XFBIN.\n'
        'Should be the same as the path of the texture in the XFBIN to inject to.\n'
        'Example: "c/1nrt/tex/1nrtbody.nut"',
    )

    texture_count: IntProperty()
    
    textures: CollectionProperty(type=NutTexturePropertyGroup)

    texture_index: IntProperty()

    def update_name(self):
        self.name = self.texture_name

    def init_data(self, chunk: NuccChunkTexture):
        self.texture_name = chunk.name
        self.path = chunk.filePath
        self.nut: Nut = chunk.nut
        self.texture_count = len(self.nut.textures)
        
        self.textures.clear()
        for i, nut_texture in enumerate(self.nut.textures):
            texture = self.textures.add()
            texture.init_data(nut_texture, f'{self.texture_name}_{i}', self.path)

    include: BoolProperty(
        name='Include in XFBIN',
        description='Repack the texture into the XFBIN when exporting.\n'
        'This should be enabled for all textures that are specific to the XFBIN '
        '(i.e. celshade/haching etc should not be included).\n\n'
        'Note: The path to the texture in NUT format (.nut) must be provided',
    )

    nut_path: StringProperty(
        name='NUT Path',
    )


class TextureChunksListPropertyGroup(PropertyGroup):
    texture_chunks: CollectionProperty(
        type=XfbinTextureChunkPropertyGroup,
    )

    texture_chunk_index: IntProperty()

    def init_data(self, texture_chunks: List[NuccChunkTexture]):
        #self.texture_chunks.clear()
        for texture in texture_chunks:
            t: XfbinTextureChunkPropertyGroup = self.texture_chunks.add()
            t.init_data(texture)


class XFBIN_PANEL_OT_OpenNut(bpy.types.Operator):
    """Open a NUT texture to include in the XFBIN"""
    bl_idname = 'xfbin_panel.open_nut'
    bl_label = 'Open NUT (*.nut)'

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.nut', options={'HIDDEN'})

    def execute(self, context):
        data: TextureChunksListPropertyGroup = context.object.xfbin_texture_chunks_data
        chunks = data.texture_chunks
        index = data.texture_chunk_index

        if not chunks:
            # Should not happen
            return {'CANCELLED'}

        chunks[index].nut_path = self.filepath

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)

        return {'RUNNING_MODAL'}


class XfbinTextureChunkPropertyPanel(Panel):
    bl_idname = 'OBJECT_PT_xfbin_texture_chunk_list'
    bl_label = '[XFBIN] Texture Chunks'

    bl_space_type = 'PROPERTIES'
    bl_context = 'object'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'EMPTY' and obj.parent is None and obj.name.startswith(XFBIN_TEXTURES_OBJ)

    def draw(self, context):
        layout = self.layout
        obj = context.object
        data: TextureChunksListPropertyGroup = obj.xfbin_texture_chunks_data

        layout.label(text='NUT List:')

        draw_xfbin_list(layout, 0, data, f'xfbin_texture_chunks_data', 'texture_chunks', 'texture_chunk_index')
        index = data.texture_chunk_index

        if data.texture_chunks and index >= 0:
            texture_chunk: XfbinTextureChunkPropertyGroup = data.texture_chunks[index]
            box = layout.box()

            #add 2 properties next to each other
            row = box.row()
            row.prop(texture_chunk, 'texture_name')
            row = box.row()
            row.prop(texture_chunk, 'path')


        if len(data.texture_chunks) > 0:
            tex = data.texture_chunks[data.texture_chunk_index]
            layout.label(text='NUT Textures List:')
            draw_xfbin_list(layout, 1, tex, f'xfbin_texture_chunks_data.texture_chunks{[data.texture_chunk_index]}', 'textures', 'texture_index')

            box = layout.box()
            if tex.textures:
                index = tex.texture_index
                if index >= 0:
                    texture: NutTexturePropertyGroup = tex.textures[index]
                    row = box.row()
                    if texture.image is not None:
                        row.template_ID_preview(texture, 'image', open='image.open')
                        row.scale_y = 1.2

                    row = box.row()
                    row.enabled = False
                    
                    row.label(text = f'Width: {texture.image.size[0] if texture.image is not None else "None"}')
                    row.label(text = f'Height: {texture.image.size[1] if texture.image is not None else "None"}')
                    row.label(text = f'Format: {Pixel_Formats.get(texture.image["nut_pixel_format"] if "nut_pixel_format" in texture.image else None) if texture.image else "None"}')
                    row.label(text = f'Mipmaps: {texture.image["nut_mipmaps_count"] if "nut_mipmaps_count" in texture.image else "None"}' if texture.image else "Mipmaps: None")

                    
                    row = box.row()
                    row.prop_search(texture, 'image', bpy.data, 'images')
                    row.operator('xfbin_panel.open_image', icon='FILEBROWSER')
                                        

class XFBIN_PANEL_OT_OpenImage(bpy.types.Operator):
    """Open an image to include in the NUT"""
    bl_idname = 'xfbin_panel.open_image'
    bl_label = 'Open Image (*.dds)'

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.dds', options={'HIDDEN'})

    def execute(self, context):
        data: TextureChunksListPropertyGroup = context.object.xfbin_texture_chunks_data
        chunks = data.texture_chunks
        index = data.texture_chunk_index

        if not chunks:
            # Should not happen
            return {'CANCELLED'}

        texture_chunk: XfbinTextureChunkPropertyGroup = chunks[index]
        textures = texture_chunk.textures
        texture_index = texture_chunk.texture_index

        if not textures:
            # Should not happen
            return {'CANCELLED'}

        texture: NutTexturePropertyGroup = textures[texture_index]
        #load the image
        with open(self.filepath, 'rb') as ddsf:
            texdata: dds.DDS = dds.read_dds(ddsf.read())

            #check if the dds is in a supported format
            if texdata.header.pixel_format.fourCC in dds.nut_pf_fourcc.keys():
                texture.pixel_format = dds.nut_pf_fourcc[texdata.header.pixel_format.fourCC]
            
            elif texdata.header.pixel_format.bitmasks in dds.nut_pf_bitmasks.keys():
                texture.pixel_format = dds.nut_pf_bitmasks[texdata.header.pixel_format.bitmasks]
            
            else:
                self.report({'ERROR'}, 'Unsupported DDS format. DDS file must be in one of the following formats:\n'
                'DXT1, DXT3, DXT5, B5G6R5, B5G5R5A1, B4G4R4A4, B8G8R8A8')
                return {'CANCELLED'}

        #load and pack the image
        image = bpy.data.images.load(self.filepath)
        image.alpha_mode = 'STRAIGHT'
        image.name = self.filepath.split('\\')[-1][:-4]
        image.filepath = texture_chunk.nut_path
        image.filepath_raw = self.filepath
        image.pack()
        image.source = 'FILE'
        #add custom properties to the image
        image['nut_pixel_format'] = texture.pixel_format
        image['nut_mipmaps_count'] = texdata.header.mipMapCount


        texture.image = image
        texture.name = image.name
        texture.width = texdata.header.width
        texture.height = texdata.header.height


        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)

        return {'RUNNING_MODAL'}
        

class RemakeShaders(bpy.types.Operator):
    bl_idname = "object.remake_shaders"
    bl_label = "Remake Shaders"
    bl_description = 'Delete the current shaders and remake them, this is useful for when you import a texture file'
    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'EMPTY' and obj.parent is None and obj.name.startswith(XFBIN_TEXTURES_OBJ)
    
    def execute(self, context):
        #Shader functions
        shaders_dict = {'00 00 F0 0A': F00A, '00 01 F0 0A': F00A, '00 02 F0 0A': _02_F00A, '00 05 F0 0D': _05_F00D,
        '00 01 F0 0D': _05_F00D, '00 01 F0 03': _01_F003, '00 05 F0 03': _01_F003, '00 05 F0 02': _05_F002, '00 07 F0 02':_07_F002,
        '00 00 E0 02': E002, '00 07 F0 10':_07_F010, '00 03 F0 10':_07_F010, '00 07 F0 0D':_07_F00D, '00 01 F0 02':_01_F002,
        '00 01 F0 08':_01_F008,}
        objects = [o for o in context.object.users_collection[0].objects if o.type == 'MESH']
        for o in objects:
            parent = o.parent.parent
            xfbin_mat = parent.xfbin_clump_data.materials[o.xfbin_mesh_data.xfbin_material]
            if f'[XFBIN] {xfbin_mat.name}' in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials.get(f'[XFBIN] {xfbin_mat.name}'))


        for o in objects:
            parent = o.parent.parent
            if o.xfbin_mesh_data.materials[0].name in shaders_dict:
                meshmat = o.xfbin_mesh_data.materials[0]
                xfbin_mat = parent.xfbin_clump_data.materials[o.xfbin_mesh_data.xfbin_material]
                if f'[XFBIN] {xfbin_mat.name}' not in bpy.data.materials:
                    material = shaders_dict.get(o.xfbin_mesh_data.materials[0].name)(self, meshmat, xfbin_mat, f'[XFBIN] {xfbin_mat.name}', xfbin_mat.name)
                    o.material_slots[0].material = material
                else:
                    o.material_slots[0].material = bpy.data.materials[f'[XFBIN] {xfbin_mat.name}']
            else:
                xfbin_mat = parent.xfbin_clump_data.materials[o.xfbin_mesh_data.xfbin_material]

                material = bpy.data.materials.new(f'[XFBIN] {xfbin_mat.name}')
                material.use_nodes = True
                material.blend_method = 'CLIP'
                material.shadow_method = 'CLIP'

                #remove node groups with the same name to prevent issues with min and max values of some nodes
                if bpy.data.node_groups.get(xfbin_mat.name):
                    bpy.data.node_groups.remove(bpy.data.node_groups.get(xfbin_mat.name))
                

                if xfbin_mat.texture_groups and xfbin_mat.texture_groups[0].textures:
                    #texcount = len(xfbin_mat.texture_groups[0].textures)
                    not_included = ['celshade', 'haching', 'haching1', 'haching2', 'haching_n', '1efc_pro_noise01']
                    prev_index = 0
                    for i in range(len(xfbin_mat.texture_groups[0].textures)):
                        if i == 0:
                            globals()[f'image_name_{i}'] = xfbin_mat.texture_groups[0].textures[i].texture
                            globals()[f'uv_{i}'] = material.node_tree.nodes.new('ShaderNodeUVMap')
                            globals()[f'uv_{i}'].uv_map = f'UV_{i}'
                            globals()[f'tex_{i}'] = material.node_tree.nodes.new('ShaderNodeTexImage')
                            globals()[f'tex_{i}'].name = f'Texture_{i}'
                            globals()[f'tex_{i}'].image = bpy.data.images.get(globals()[f'image_name_{i}'])
                            material.node_tree.links.new(globals()[f'uv_{i}'].outputs[0], globals()[f'tex_{i}'].inputs[0])
                            pBSDF = material.node_tree.nodes.get('Principled BSDF')
                            material.node_tree.links.new(globals()[f'tex_{i}'].outputs[0], pBSDF.inputs['Base Color'])
                            material.node_tree.links.new(globals()[f'tex_{i}'].outputs[1], pBSDF.inputs['Alpha'])
                            prev_index = i
                            print(prev_index)
                        if i > 0 and xfbin_mat.texture_groups[0].textures[i].texture_name not in not_included:
                            globals()[f'image_name_{i}'] = xfbin_mat.texture_groups[0].textures[i].texture
                            globals()[f'uv_{i}'] = material.node_tree.nodes.new('ShaderNodeUVMap')
                            globals()[f'uv_{i}'].uv_map = f'UV_{i}'
                            globals()[f'tex_{i}'] = material.node_tree.nodes.new('ShaderNodeTexImage')
                            globals()[f'tex_{i}'].name = f'Texture_{i}'
                            globals()[f'tex_{i}'].image = bpy.data.images.get(globals()[f'image_name_{i}'])
                            globals()[f'mix_{i}'] = material.node_tree.nodes.new('ShaderNodeMixRGB')
                            globals()[f'mix_{i}'].blend_type = 'MIX'
                            globals()[f'mix_{i}'].inputs[0].default_value = 1
                            material.node_tree.links.new(globals()[f'uv_{i}'].outputs[0], globals()[f'tex_{i}'].inputs[0])
                            material.node_tree.links.new(globals()[f'tex_{i}'].outputs[1], globals()[f'mix_{i}'].inputs[0])
                            material.node_tree.links.new(globals()[f'tex_{prev_index}'].outputs[0], globals()[f'mix_{i}'].inputs[1])
                            material.node_tree.links.new(globals()[f'tex_{i}'].outputs[0], globals()[f'mix_{i}'].inputs[2])
                            material.node_tree.links.new(globals()[f'mix_{i}'].outputs[0], pBSDF.inputs['Base Color'])
                            prev_index += 1
                            print(prev_index)
                o.material_slots[0].material = material
            
        return {'FINISHED'}


texture_chunks_property_groups = (
    NutTexturePropertyGroup,
    XfbinTextureChunkPropertyGroup,
    TextureChunksListPropertyGroup,
)

texture_chunks_classes = (
    *texture_chunks_property_groups,
    XFBIN_PANEL_OT_OpenNut,
    XFBIN_PANEL_OT_OpenImage,
    XfbinTextureChunkPropertyPanel,
    RemakeShaders,
    
)
