from typing import List, Optional

import bpy
from bpy.props import (BoolProperty, CollectionProperty, IntProperty,
                       StringProperty)
from bpy.types import Action, Panel, PropertyGroup

from ...xfbin_lib.xfbin.structure.nucc import NuccChunkAnm, NuccChunkCamera
from ...xfbin_lib.xfbin.structure.anm import AnmClump, AnmBone, AnmModel, AnmKeyframe
from ..common.helpers import XFBIN_ANMS_OBJ
from ..importer import make_actions
from .common import draw_xfbin_list


class CameraPropertyGroup(PropertyGroup):
    def update_camera_name(self, context):
        self.update_name()

    name: StringProperty(
        name="Name",
        default='new_camera',
        update=update_camera_name,
    )

    path: StringProperty(name="Path")

    camera_index: IntProperty(name="Index")

    def update_name(self):
        self.name = self.name

    def init_data(self, camera: Optional[NuccChunkCamera] = None):
        if camera:
            self.name = camera.name
            self.path = camera.filePath




class AnmClumpBonePropertyGroup(PropertyGroup):
    name: StringProperty()

    def init_data(self, bone: AnmBone):
        self.name = bone.name

class AnmClumpModelPropertyGroup(PropertyGroup):
    def update_model_name(self, context):
        self.update_name()

    model_name: StringProperty(
        name="Name",
        default='new_model',
        update=update_model_name,
    )

    def update_name(self):
        self.name = self.model_name

    def init_data(self, model: AnmModel):
        self.name = model.name


class AnmClumpPropertyGroup(PropertyGroup):
    def update_name(self, context):
        self.update_name()

    name: StringProperty(
        name="Name",
        default='new_clump',
        update=update_name,
    )

    clump_index: IntProperty(name="Clump Index")
    models: CollectionProperty(type=AnmClumpModelPropertyGroup)
    model_index: IntProperty(name="Model Index")
    bones: CollectionProperty(type=AnmClumpBonePropertyGroup)
    bone_index: IntProperty(name="Bone Index")

    def update_name(self):
        self.name = self.name

    def init_data(self, clump: AnmClump):
        self.name = clump.name
        
        self.models.clear()
        for model in clump.models:
            item = self.models.add()
            item.init_data(model)
        
        self.bones.clear()
        for bone in clump.bones:
            item = self.bones.add()
            item.init_data(bone)
        


class XfbinAnmChunkPropertyGroup(PropertyGroup):
    def update_anm_name(self, context):
        self.update_name()

    anm_name: StringProperty(
        name="Name",
        default='new_anm',
        update=update_anm_name,
    )

    path: StringProperty(name="Path")

    is_looped: BoolProperty(name="Looped", default=False)

    frame_count: IntProperty(name="Frame Count", default=0)

    frame_size: IntProperty(name="Frame Size", default=100)

    clump_index: IntProperty()

    anm_clumps: CollectionProperty(
        type=AnmClumpPropertyGroup,
    )

    camera_index: IntProperty()

    cameras: CollectionProperty(
        type=CameraPropertyGroup,
    )

    def update_name(self):
        self.name = self.anm_name

    def init_data(self, anm: NuccChunkAnm, camera: Optional[NuccChunkCamera], actions: List[Action] = None):
        self.anm_name = anm.name
        self.path = anm.filePath
        self.is_looped = anm.loop_flag
        self.frame_count = anm.frame_count // anm.frame_size
        self.frame_size = anm.frame_size

        self.anm_clumps.clear()
        for clump in anm.clumps:
            clump_prop: AnmClumpPropertyGroup = self.anm_clumps.add()
            clump_prop.init_data(clump)

        self.cameras.clear()
        if camera:
            camera_prop: CameraPropertyGroup = self.cameras.add()
            camera_prop.init_data(camera)
     

    


class AnmChunksListPropertyGroup(PropertyGroup):
    anm_chunks: CollectionProperty(
        type=XfbinAnmChunkPropertyGroup,
    )

    anm_chunk_index: IntProperty()

    def init_data(self, anm_chunks: List[NuccChunkAnm], cam_chunks: List[NuccChunkCamera], context):
        self.anm_chunks.clear()

        for anm in anm_chunks:
            has_camera = False

            for cam in cam_chunks:
                if anm.filePath == cam.filePath:
                    has_camera = True
                    a: XfbinAnmChunkPropertyGroup = self.anm_chunks.add()
                    a.init_data(anm, cam, make_actions(anm, context))
                    break

            if not has_camera:
                a: XfbinAnmChunkPropertyGroup = self.anm_chunks.add()
                a.init_data(anm, None, make_actions(anm, context))

class AnmChunksPropertyPanel(Panel):

    bl_idname = 'OBJECT_PT_xfbin_animation'
    bl_label = '[XFBIN] Animation Properties'

    bl_space_type = 'PROPERTIES'
    bl_context = 'object'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'EMPTY' and obj.parent is None and obj.name.startswith(XFBIN_ANMS_OBJ)
    
    def draw(self, context):
        obj = context.object
        layout = self.layout

        data: AnmChunksListPropertyGroup = obj.xfbin_anm_chunks_data
        
        draw_xfbin_list(layout, 0, data, 'xfbin_anm_chunks_data', 'anm_chunks', 'anm_chunk_index')
    
        box = layout.box()
        box.label(text="Animation Properties:")

        anm_index = data.anm_chunk_index

        if data.anm_chunks and anm_index >= 0 and anm_index < len(data.anm_chunks):
            anm: XfbinAnmChunkPropertyGroup = data.anm_chunks[anm_index]
            box.prop(anm, 'name')
            box.prop(anm, 'path')

            row = box.row()
            row.prop(anm, 'is_looped')
            row.prop(anm, 'frame_count')

            row = box.row()
            row.prop_search(anm, 'anm_name', bpy.data, 'actions', text="Action", icon='ACTION')
            row.operator('obj.play_animation', text='Play Animation', icon='PLAY')

            if len(anm.anm_clumps) > 0:
                clump = anm.anm_clumps[anm.clump_index]
                clump_box = layout.box()
                clump_box.label(text="Clumps:")
                clump_box.prop(clump, 'name')

                draw_xfbin_list(clump_box, 1, anm, f'xfbin_anm_chunks_data.anm_chunks[{anm_index}]', 'anm_clumps', 'clump_index')
                box = clump_box.box()
                box.prop_search(anm.anm_clumps[anm.clump_index], 'name', bpy.data, 'objects', text="Clump", icon='OBJECT_DATA')

            
            camera_box = layout.box()
            camera_box.label(text="Cameras:")
            camera = anm.cameras[anm.camera_index] if anm.cameras and anm.camera_index < len(anm.cameras) else None
            if camera:
                camera_box.prop(camera, 'name')
                camera_box.prop(camera, 'path')
                draw_xfbin_list(camera_box, 3, anm, f'xfbin_anm_chunks_data.anm_chunks[{anm_index}]', 'cameras', 'camera_index')
                box = camera_box.box()
                box.prop_search(anm.cameras[anm.camera_index], 'name', bpy.data, 'cameras', text="Camera", icon='CAMERA_DATA')
            else:
                draw_xfbin_list(camera_box, 3, anm, f'xfbin_anm_chunks_data.anm_chunks[{anm_index}]', 'cameras', 'camera_index')

class PlayAnimation(bpy.types.Operator):
    bl_idname = 'obj.play_animation'
    bl_label = 'Play Animation'
    bl_description = 'Play Animation'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'EMPTY' and obj.parent is None and obj.name.startswith(XFBIN_ANMS_OBJ)
    
    def execute(self, context):
        # Selected animation
        obj = context.object
        data: AnmChunksListPropertyGroup = obj.xfbin_anm_chunks_data
        anm_index = data.anm_chunk_index

        if anm_index >= 0 and anm_index < len(data.anm_chunks):
            anm: XfbinAnmChunkPropertyGroup = data.anm_chunks[anm_index]

            context.scene.frame_start = 0
            context.scene.frame_end = anm.frame_count
            context.scene.frame_current = 0


            clumps: List[AnmClump] = []

            for clump in anm.anm_clumps:
                c = bpy.context.view_layer.objects.get(f'{clump.name} [C]')

                if c:
                    clumps.append(c)
   
            for clump in clumps:
                action = bpy.data.actions.get(f'{anm.name} ({clump.name[:-4]})')

                if action:
                    clump.animation_data_create()
                    clump.animation_data.action = action
                    self.report({'INFO'}, f'Playing animation {action.name}')
            
            # Check if no animation is playing
            if not context.screen.is_animation_playing:
                bpy.ops.screen.animation_play()
            
           
        
        return {'FINISHED'}




anm_chunks_property_groups = (
    AnmClumpBonePropertyGroup,
    AnmClumpModelPropertyGroup,
    AnmClumpPropertyGroup,
    CameraPropertyGroup,
    XfbinAnmChunkPropertyGroup,
    AnmChunksListPropertyGroup,
)

anm_chunks_classes = (
    *anm_chunks_property_groups,
    AnmChunksPropertyPanel,
    PlayAnimation,
)
